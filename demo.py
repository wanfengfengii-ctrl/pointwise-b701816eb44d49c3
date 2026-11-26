import json
from pathlib import Path
from tempfile import TemporaryDirectory

from mix.service import BroadcastService
from tests.support import running_service


def run_branch(api, show, version_a, version_b, stop_a):
    api.scene('opening', 'left', 2, show)
    cue_a = api.cue(version_a, 0, show=show)
    first = api.emit(0, show)
    api.scene('next', 'right', 1, show)
    api.cue(version_b, 2, show=show)
    if stop_a:
        stopped = api.stop(cue_a, show)
        if stopped != {'cue_id': cue_a, 'stopped': True}:
            raise AssertionError(f'unexpected stop response: {stopped!r}')
    aired = [first] + [api.emit(frame, show) for frame in range(1, 4)]
    replayed = api.replay(0, 3, show)
    looked_up = api.read(0, show)
    expected = [[8, 0], [0, 0], [6 if stop_a else 10, 0], [0, 6]]
    expected_records = [
        {'show': show, 'frame': frame, 'left': levels[0], 'right': levels[1]}
        for frame, levels in enumerate(expected)
    ]
    if aired != expected_records or replayed != expected_records or looked_up != expected_records[0]:
        raise AssertionError(f'{show}: expected {expected_records!r}, aired {aired!r}, replay {replayed!r}, lookup {looked_up!r}')
    evidence = {
        'case_id': 'T6' if stop_a else 'T5',
        'input': {'show': show, 'A': {'sample': 8, 'dry_frame': 0, 'output': 'left'},
                  'opening': {'echo_output': 'left', 'echo_delay': 2},
                  'next': {'echo_output': 'right', 'echo_delay': 1},
                  'B': {'sample': 6, 'dry_frame': 2, 'output': 'left'}, 'stop_a': stop_a},
        'expected': expected_records,
        'actual': aired,
        'downstream_expected': {'replay': expected_records, 'first': expected_records[0]},
        'downstream_actual': {'replay': replayed, 'first': looked_up},
        'code_paths': ['cues/accept.py', 'cues/stop.py', 'mix/timeline.py', 'mix/emit.py', 'aircheck/replay.py'],
        'oracle': 'Manual frame placement gives A at left 0 and left 2, B at left 2 and right 3. At left 2, 8+6 clips to 10, or only B contributes 6 if A stopped. Frame 1 is silent.',
    }
    print('POINTWISE_SCENARIO ' + json.dumps(evidence, ensure_ascii=False, separators=(',', ':')))


def main():
    with TemporaryDirectory(prefix='live-mix-demo-') as directory:
        service = BroadcastService(Path(directory) / 'demo.sqlite')
        service.prepare_show('keep')
        service.prepare_show('stop')
        with running_service(service) as api:
            a = api.asset('A', 8)
            b = api.asset('B', 6)
            for version, name, sample in ((a, 'A', 8), (b, 'B', 6)):
                expected = {'version': version, 'name': name, 'sample': sample}
                actual = api.preview(version)
                if actual != expected:
                    raise AssertionError(f'preview: expected {expected!r}, got {actual!r}')
            run_branch(api, 'keep', a, b, False)
            run_branch(api, 'stop', a, b, True)


if __name__ == '__main__':
    main()
