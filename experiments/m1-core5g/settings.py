"""Frozen sources, evidence, and reusable CORE-5F mechanics."""
from pathlib import Path
import sys
G=Path(__file__).resolve().parent
sys.path.insert(0,str(G.parent/"m1-core5f"))
from common import ROOT,INFRA,H5,read,save,load,digest,sha,scan,deck_for,utility,expected,torch
from data import Data
from fit5d import logits,differences
from fit5e import base_net
from semantic import Value
from targets5e import terminal_target
A=INFRA/"experiments/m1-infra2a"
OUT=G/"evidence"
WORK=ROOT/"logs/core5g"
OUT.mkdir(exist_ok=True)
WORK.mkdir(parents=True,exist_ok=True)
RELEASE="dc7985a66a7cc0de2ac2a85f5dfa95cd804dc061286e366a7211bb1db43d4bb2"
BEHAVIOR="51ed7db73b4d583c183d5a37bbcb6a2f3585bc73cd4cb931774fee46b8e32616"
POLICY="25740c4a3b29a5f378f6bd5723d3b594be6547a77e16b891e461bbf2bfcdcda7"
