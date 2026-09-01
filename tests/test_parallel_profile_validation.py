import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from profiling.adaptive_walltime_profile import (
    BPLSD_OPTIONS,
    PickleableBPLSDGenerator,
    _arg_parser,
    run as run_profile,
)
from validation.adaptive_forced_long_repro import run_validation
from validation.knill_repro_common import ValidationConfig, configuration_signature


def test_parallel_profile_arguments_and_factory_are_spawn_safe():
    args = _arg_parser().parse_args(
        ["--num-workers", "2", "--warmup-shots", "0", "--checkpoint-path", "checkpoint.json"]
    )
    assert args.num_workers == 2
    assert args.warmup_shots == 0
    assert args.checkpoint_path == Path("checkpoint.json")
    pickle.dumps(
        PickleableBPLSDGenerator(
            0.003,
            alpha=2.0,
            decoder_options=BPLSD_OPTIONS,
        )
    )


def test_parallel_profile_writes_aggregate_artifacts(tmp_path):
    args = _arg_parser().parse_args([
        "--distance", "3",
        "--physical-error", "0.0",
        "--short-rounds", "1",
        "--long-rounds", "2",
        "--num-shots", "1",
        "--warmup-shots", "0",
        "--num-workers", "1",
        "--initial-chunk-shots", "1",
        "--max-chunk-shots", "1",
        "--output-dir", str(tmp_path),
        "--output-prefix", "parallel_test",
    ])
    result = run_profile(args)
    assert result.shots == 1
    assert (tmp_path / "parallel_test_parallel_summary.csv").exists()
    report = (tmp_path / "parallel_test_parallel_report.md").read_text()
    assert "Parent wall time" in report
    assert "worker-local `WallTimeProfiler` events are not collected" in report


def test_parallel_adaptive_validation_runs_and_keeps_signature_stable(tmp_path):
    serial_config = ValidationConfig(
        distances=(3,),
        physical_errors=(0.0,),
        shots=256,
        output_dir=tmp_path / "serial",
    )
    parallel_config = ValidationConfig(
        distances=(3,),
        physical_errors=(0.0,),
        shots=256,
        output_dir=tmp_path,
        parallel_num_workers=1,
        parallel_initial_chunk_shots=1,
        parallel_max_chunk_shots=32,
    )
    assert configuration_signature(
        "adaptive_forced_long_repro", serial_config
    ) == configuration_signature("adaptive_forced_long_repro", parallel_config)

    rows, comparisons = run_validation(parallel_config)
    adaptive_rows = [row for row in rows if row["workflow"] == "adaptive_forced_long"]
    assert len(adaptive_rows) == 1
    assert int(adaptive_rows[0]["shots"]) == 256
    assert float(adaptive_rows[0]["pair_fallback_rate"]) == 1.0
    assert float(adaptive_rows[0]["mean_effective_rounds"]) == 3.0
    assert comparisons
