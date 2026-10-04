#!/usr/bin/env bash
# Shared validation for image names and release references; no network or mutations.

validate_release_tag() {
    if [[ ! "$1" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$ ]] || ((${#1} > 128)); then
        echo 'Expected a release tag such as v0.1.0 or v0.1.0-rc.1' >&2
        return 2
    fi
}

validate_image_tag() {
    [[ "$1" =~ ^[0-9a-f]{12}$ ]] || validate_release_tag "$1"
}
