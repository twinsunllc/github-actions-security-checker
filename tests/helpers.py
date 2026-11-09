"""Shared fakes for the unit tests: canned GitHub pages and a URL router
standing in for requests.get."""
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

import requests  # noqa: E402


def repo_page(listing):
    """A repository page that links to its Marketplace listing."""
    return f'<html><a href="/marketplace/actions/{listing}">View on Marketplace</a></html>'


def marketplace_page(owner, verified=True):
    """A Marketplace listing, with or without the verified creator badge."""
    badge = ('<span>Verified</span><p>GitHub has manually verified the creator of the action '
             'as an official partner organization.</p>') if verified else ''
    return f'<html>{badge}<a href="/{owner}">{owner}</a></html>'


def response(status, text=''):
    resp = mock.Mock(spec=requests.Response)
    resp.status_code = status
    resp.text = text
    return resp


class Router:
    """requests.get stand-in. Each URL maps to a list of outcomes (a
    response or an exception), consumed in order; the last one repeats."""

    def __init__(self, routes):
        self.routes = {url: list(outcomes) for url, outcomes in routes.items()}
        self.calls = []

    def __call__(self, url, timeout=None):
        self.calls.append(url)
        outcomes = self.routes.get(url)
        if outcomes is None:
            raise AssertionError(f'unexpected fetch of {url}')
        outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def count(self, url):
        return self.calls.count(url)


def verified_docker_routes(action='build-push-action', listing='build-and-push-docker-images'):
    return {
        f'https://github.com/docker/{action}': [response(200, repo_page(listing))],
        f'https://github.com/marketplace/actions/{listing}': [response(200, marketplace_page('docker'))],
    }
