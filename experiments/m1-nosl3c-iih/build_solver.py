"""Build II-H on top of II-G Completion in a separate output directory."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
BASE = runpy.run_path(str(HERE.parent / "m1-nosl3c-iig-completion/build_solver.py"))
edit = BASE["edit"]
VERSION = "0.51.5-iih.1"


def history_window(source):
    sim = source / "Engine/InCombat/Simulation"
    entries = sim / "CombatPredictionHistoryEntry.cs"
    edit(entries, "    public int Index { get; set; }",
         """    public int Index { get; set; }
    public (MegaCrit.Sts2.Core.Combat.CombatSide Side, int Round)? CardWindow { get; set; }""")
    history = sim / "CombatPredictionHistory.cs"
    for signature in ("PredictedCard card, bool fromHandDraw", "PredictedCard card, CardPlay cardPlay"):
        edit(history, signature + ")\n    {",
             signature + ", (MegaCrit.Sts2.Core.Combat.CombatSide, int)? window = null)\n    {")
    edit(history, "            FromHandDraw = fromHandDraw", "            CardWindow = window,\n            FromHandDraw = fromHandDraw")
    edit(history, "            CardPlay = cardPlay\n", "            CardWindow = window,\n            CardPlay = cardPlay\n")
    for suffix in ("CardContinuation", "ExecutionContinuation"):
        file = sim / f"CombatPredictionHistory.{suffix}.cs"
        edit(file, "            copy.Trace =", "            copy.CardWindow = entry.CardWindow;\n            copy.Trace =")
    for file, invocation in [
        ("CardPile", "History.CardDrawn(card, fromHandDraw"),
        ("CardExecutionContinuation", "History.CardPlayStarted(card, activePlay"),
    ]:
        edit(sim / f"CombatPredictionSimulator.{file}.cs", invocation + ")",
             invocation + ", (State.CombatState.CurrentSide, State.CombatState.RoundNumber))")

    card_history = source / "Search/SimulatedCombatState.CardEventHistory.cs"
    edit(card_history, "AppendPredictedTurnCardHistory(StringBuilder text, Player player)\n    {",
         """AppendPredictedTurnCardHistory(StringBuilder text, Player player, CombatPredictionHistory history)
    {
        if (CurrentSide == CombatSide.Enemy)
        {
            // Native history filters by the current side and round. Keep the
            // player's logical counters intact for card and Power mechanics.
            var window = (CurrentSide, RoundNumber);
            var starts = history.Entries.OfType<CombatPredictionCardPlayStartedEntry>()
                .Where(entry => entry.CardWindow == window && entry.Card.Owner == player).ToArray();
            int statusDraws = history.Entries.OfType<CombatPredictionCardDrawnEntry>()
                .Count(entry => entry.CardWindow == window && entry.Card.Owner == player
                    && entry.Card.Type == CardType.Status)
                + _rootHistory.CardsDrawn.Count(entry => entry.HappenedThisTurn(this)
                    && entry.Actor.Player == player && entry.Card.Type == CardType.Status);
            var rootStarts = _rootHistory.CardPlaysStarted
                .Where(entry => entry.HappenedThisTurn(this) && entry.CardPlay.Player == player).ToArray();
            int attacks = starts.Count(entry => entry.Card.Type == CardType.Attack)
                + rootStarts.Count(entry => entry.CardPlay.Card.Type == CardType.Attack);
            AppendTurnCardHistory(text, statusDraws,
                starts.Count(entry => entry.Card.Type == CardType.Attack && entry.CardPlay.Resources.EnergyValue == 0)
                    + rootStarts.Count(entry => entry.CardPlay.Card.Type == CardType.Attack
                        && entry.CardPlay.Resources.EnergyValue == 0),
                starts.Length + rootStarts.Length,
                starts.Count(entry => entry.Card.Type is CardType.Attack or CardType.Skill)
                    + rootStarts.Count(entry => entry.CardPlay.Card.Type is CardType.Attack or CardType.Skill));
            text.Append(";FlameHp=").Append(_brightestFlameMaxHpSpent);
            text.Append(";AttackStarts=").Append(attacks);
            return;
        }""")
    edit(source / "Runtime/ContinuationStamp.cs", "combat.AppendPredictedTurnCardHistory(text, player);",
         "combat.AppendPredictedTurnCardHistory(text, player, simulator.History);")


def stage(command, **kwargs):
    iig = BASE["IIG"]
    iid = iig["IID"]["stage"]

    def compile_staged(args, **options):
        history_window(Path(args[2]).parent / "src")
        iid(args, **options)

    completion = BASE["stage"]
    FunctionType(completion.__code__, completion.__globals__ |
                 {"IIG": iig | {"IID": {"stage": compile_staged}}})(command, **kwargs)


if __name__ == "__main__":
    main = BASE["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ |
                 dict(VERSION=VERSION, subprocess=SimpleNamespace(run=stage)))()
