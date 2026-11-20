"""Build an isolated native host for reward-boundary auditing."""
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
COMPLETION = runpy.run_path(str(HERE.parent / "m1-nosl3c-iig-completion/build_host.py"))
HOST = "m1-nosl3c-iih-reward-build"


def stage(src):
    COMPLETION["stage"](src)
    program = src / "Program.cs"
    text = program.read_text(encoding="utf-8")
    old = 'or "skip_card_reward"))'
    if text.count(old) != 1:
        raise ValueError("Unexpected synthetic action allowlist")
    program.write_text(text.replace(old, 'or "skip_card_reward" or "select_card_reward"))'), encoding="utf-8")
    probe = src / "IntegrationProbe.cs"
    text = probe.read_text(encoding="utf-8")
    anchor = '        if (command == "i1_iib_native_stamp")'
    if text.count(anchor) != 1:
        raise ValueError("Unexpected native stamp dispatch")
    probe.write_text(text.replace(anchor, '''        if (command == "i1_iih_reward_snapshot")
            return sim.RewardAuditSnapshot();
''' + anchor), encoding="utf-8")
    synthetic = src / "SyntheticCombat.cs"
    text = synthetic.read_text(encoding="utf-8")
    anchor = '    internal Dictionary<string, object?> SyntheticSnapshot()'
    if text.count(anchor) != 1:
        raise ValueError("Unexpected synthetic snapshot contract")
    synthetic.write_text(text.replace(anchor, '''    internal Dictionary<string, object?> RewardAuditSnapshot()
    {
        var run = _runState ?? throw new InvalidOperationException("No synthetic run");
        var player = run.Players.Single();
        return new()
        {
            ["type"] = "reward_audit",
            ["player"] = PlayerSummary(player),
            ["run_rng"] = JsonSerializer.SerializeToElement(run.Rng.ToSerializable(), SyntheticRngJson),
            ["player_rng"] = JsonSerializer.SerializeToElement(player.PlayerRng.ToSerializable(), SyntheticRngJson),
            ["room"] = run.CurrentRoom?.RoomType.ToString(),
            ["visited_map_nodes"] = run.VisitedMapCoords.Count,
        };
    }

''' + anchor), encoding="utf-8")


if __name__ == "__main__":
    base = COMPLETION["IIG"]["BASE"]["BASE"]["BASE"]["BASE"]["BINDING"].b1b.b1a.i1
    base.build(base.ROOT / "logs" / HOST, stage)
