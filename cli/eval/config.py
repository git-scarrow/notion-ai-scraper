"""Evaluation matrix configuration: models, roles, essays, timeouts."""

import os

# ── Models ────────────────────────────────────────────────────────────────────

MODELS_PASS1 = [
    ("oval-kumquat-medium", "GPT-5.4"),
    ("oatmeal-cookie", "GPT-5.2"),
    ("anthropic-haiku-4.5", "Haiku 4.5"),
    ("gingerbread", "Gemini 3 Flash"),
    ("fireworks-minimax-m2.5", "MiniMax M2.5"),
]

# Anthropic flagships — run as supplemental pass to complete the comparison
MODELS_ANTHROPIC = [
    ("avocado-froyo-medium", "Opus 4.6"),
    ("almond-croissant-low", "Sonnet 4.6"),
]

# ── Roles ─────────────────────────────────────────────────────────────────────

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))

ROLES = {
    "structural": {
        "agent": "eval_structural_editor",
        "instructions": os.path.join(EVAL_DIR, "roles", "structural_editor.md"),
    },
    "frame": {
        "agent": "eval_frame_editor",
        "instructions": os.path.join(EVAL_DIR, "roles", "frame_editor.md"),
    },
    "evidence": {
        "agent": "eval_evidence_editor",
        "instructions": os.path.join(EVAL_DIR, "roles", "evidence_editor.md"),
    },
}

# ── Essays ────────────────────────────────────────────────────────────────────

ESSAYS = {
    "tearing-of-the-page": os.path.join(EVAL_DIR, "essays", "tearing-of-the-page.md"),
    "unbelievable-story": os.path.join(EVAL_DIR, "essays", "unbelievable-story.md"),
    "gilded-age": os.path.join(EVAL_DIR, "essays", "gilded-age.md"),
}

# Pass 1 uses only the first essay; Pass 2 uses all three
PASS1_ESSAYS = ["tearing-of-the-page"]
PASS2_ESSAYS = list(ESSAYS.keys())

# ── Timing ────────────────────────────────────────────────────────────────────

TIMEOUT = 300       # 5 min per inference run
COOLDOWN = 30       # seconds between runs (avoid Notion back-pressure)
POLL_INTERVAL = 5   # seconds between response polls

# ── Scoring dimensions ───────────────────────────────────────────────────────

SCORING_RUBRIC = {
    "structural": [
        "contribution_accuracy",
        "macro_form_classification",
        "section_role_precision",
        "reader_question_ordering",
        "red_line_preservation",
    ],
    "frame": [
        "frame_identification",
        "concept_slippage_detection",
        "counterpressure_quality",
        "ending_type_accuracy",
        "shown_vs_named_sensitivity",
    ],
    "evidence": [
        "claim_extraction_accuracy",
        "support_status_accuracy",
        "missing_attribution",
        "projection_vs_fact_discipline",
        "publication_risk_prioritization",
    ],
}
