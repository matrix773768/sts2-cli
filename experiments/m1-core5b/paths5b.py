"""An optional fresh run directory keeps reproduced evidence separate from the archived study."""
import os
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
override=os.environ.get("STS2_CORE5B_RUN")
RUN=Path(override).resolve() if override else None
E=(RUN if RUN else HERE)/"evidence"
LOGS=(RUN if RUN else ROOT)/"logs"
