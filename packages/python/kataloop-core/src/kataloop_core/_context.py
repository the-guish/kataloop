# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""What of the conversation a model call sends: the seam of context management.

Every model call of a turn sends `fit(messages, model)` (TURN-3). Context
management, ENG-12, is step 6 of docs/plan.md and lands here: summarising older
turns past a share of the window, cutting tool results above a fifth of it,
never cutting the question. Until then the conversation is sent whole, and one
longer than the model's window fails at the vendor.
"""

from __future__ import annotations

from collections.abc import Sequence

from uni_llm_client import Message

from kataloop_core._contract import ModelSpec


def fit(messages: Sequence[Message], model: ModelSpec) -> Sequence[Message]:
    """The messages to send `model`, kept within its window (ENG-12): for now,
    all of them."""
    return messages
