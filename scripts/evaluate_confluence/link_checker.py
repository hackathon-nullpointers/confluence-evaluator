"""Normalize and validate external links from page content."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from .constants import LINK_TIMEOUT, MAX_LINKS_PER_PAGE, MAX_REDIRECTS


def normalize_web_links(hrefs: list[str], page_url: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for href in hrefs:
        try:
            href = href.strip()
            if not href or href.startswith("#"):
                continue
            parsed_href = urlsplit(href)
            if parsed_href.scheme and parsed_href.scheme.lower() not in {"http", "https"}:
                continue
            target = urljoin(page_url, href)
            parsed = urlsplit(target)
        except ValueError:
            continue
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            continue
        normalized = urlunsplit(
            (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, "")
        )
        if normalized not in seen:
            seen.add(normalized)
            links.append(normalized)
    return links

def public_addresses(hostname: str, port: int) -> bool:
    try:
        literal = ipaddress.ip_address(hostname)
        addresses = [literal]
    except ValueError:
        addresses = [
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        ]
    return bool(addresses) and all(
        (getattr(address, "ipv4_mapped", None) or address).is_global
        for address in addresses
    )

def check_one_link(session: requests.Session, initial_url: str) -> str:
    current_url = initial_url
    visited: set[str] = set()
    for _ in range(MAX_REDIRECTS + 1):
        if current_url in visited:
            return "invalid"
        visited.add(current_url)
        try:
            parsed = urlsplit(current_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                return "unchecked"
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if port not in {80, 443}:
                return "unchecked"
            try:
                is_public = public_addresses(parsed.hostname, port)
            except socket.gaierror as error:
                if error.errno in {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -999)}:
                    return "invalid"
                return "unchecked"
            except (OSError, ValueError):
                return "unchecked"
            if not is_public:
                return "unchecked"

            response = session.head(
                current_url,
                timeout=LINK_TIMEOUT,
                allow_redirects=False,
                headers={"User-Agent": "confluence-evaluator-link-checker/1.0"},
            )
            if response.status_code in {405, 501}:
                response.close()
                response = session.get(
                    current_url,
                    timeout=LINK_TIMEOUT,
                    allow_redirects=False,
                    headers={
                        "Range": "bytes=0-2047",
                        "User-Agent": "confluence-evaluator-link-checker/1.0",
                    },
                    stream=True,
                )

            if response.is_redirect:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    return "invalid"
                current_url = urljoin(current_url, location)
                continue
            status = response.status_code
            response.close()
            return "valid" if 200 <= status < 400 else "invalid"
        except requests.Timeout:
            return "unchecked"
        except requests.RequestException:
            return "unchecked"
        except ValueError:
            return "unchecked"
    return "invalid"

def check_links(urls: list[str]) -> tuple[int, int, int]:
    session = requests.Session()
    session.trust_env = False
    valid = invalid = unchecked = 0
    for url in urls[:MAX_LINKS_PER_PAGE]:
        outcome = check_one_link(session, url)
        if outcome == "valid":
            valid += 1
        elif outcome == "invalid":
            invalid += 1
        else:
            unchecked += 1
    unchecked += max(0, len(urls) - MAX_LINKS_PER_PAGE)
    session.close()
    return valid, invalid, unchecked
