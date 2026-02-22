"""Shared CLI helpers."""

from __future__ import annotations

import argparse


def base_parser(name: str, description: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=name, description=description)
