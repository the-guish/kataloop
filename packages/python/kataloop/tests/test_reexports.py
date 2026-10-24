# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""`kataloop` is the core's API, re-exported, and its extras
(docs/specs/principles.md)."""

import kataloop
import kataloop_core


def test_the_core_api_is_reexported_as_it_is() -> None:
    names = set(kataloop_core.__all__) - {"__version__"}
    extras = {"HttpClientFactory", "McpHttpClient", "McpHttpTimeout", "McpToolbox"}

    assert set(kataloop.__all__) - {"__version__"} == names | extras
    for name in names:
        assert getattr(kataloop, name) is getattr(kataloop_core, name)
