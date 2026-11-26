import http.client
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from mix.service import BroadcastService
from relay_fixture import forwarding, running_endpoint
from tests.support import StudioClient, running_service


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


def relay_demo():
    with TemporaryDirectory(prefix='live-mix-relay-demo-') as directory:
        base = Path(directory)
        playout_command = ('-m', 'playout.http', '--db', str(base / 'playout.sqlite'),
                           '--show', 'early', '--show', 'late')

        def studio_command(relay_base):
            command = ['-m', 'mix.http', '--db', str(base / 'studio.sqlite'),
                       '--show', 'studio', '--show', 'early', '--show', 'late']
            for show in ('early', 'late'):
                command += ['--relay', f'{show}={relay_base}']
            return tuple(command)

        with running_endpoint(*playout_command) as playout, forwarding(playout.port) as proxy:
            operator = StudioClient(proxy.server_port)
            with running_endpoint(*studio_command(proxy.address)) as studio:
                version = studio.asset('A', 8)
                cues = {}
                for show in ('early', 'late'):
                    studio.scene('relay-opening', 'right', 2, show)
                    cues[show] = studio.cue(version, 0, show=show)
                # early: the candidate arrives first, but its acceptance reply is lost.
                gate = proxy.intercept_once('POST', '/shows/early/candidates', drop=True)
                status, pending = studio.request(
                    'POST', '/shows/early/stage', {'frame': 0, 'request_id': 'opening-0'})
                if status != 202 or pending.get('status') != 'pending':
                    raise AssertionError(f'lost acceptance should be pending, got {status} {pending!r}')
                if not gate.finished.is_set() or gate.upstream_status != 200:
                    raise AssertionError('playout did not accept the first candidate')
                # early: frame 0 airs the program, but the aired reply is lost too.
                gate = proxy.intercept_once('POST', '/shows/early/tick', drop=True)
                try:
                    operator.request('POST', '/shows/early/tick', {'frame': 0})
                    raise AssertionError('the dropped tick reply was delivered')
                except http.client.RemoteDisconnected:
                    pass
                if not gate.finished.is_set() or gate.upstream_status != 200:
                    raise AssertionError('playout did not air frame 0')
                # late: the tick arrives first, so frame 0 airs silence.
                late_air = operator.tick(0, 'late')
                if late_air != {'show': 'late', 'frame': 0, 'left': 0, 'right': 0, 'request_id': None}:
                    raise AssertionError(f'late frame 0 should be silence, got {late_air!r}')
                late_stage = studio.stage(0, 'opening-0', 'late')
                if late_stage.get('status') != 'expired':
                    raise AssertionError(f'late candidate should be expired, got {late_stage!r}')
                # Nothing is archived at the studio before sync.
                for show in ('early', 'late'):
                    missing = studio.expect('GET', f'/shows/{show}/frames/0', 404)
                    if missing['error'] != 'frame_not_aired':
                        raise AssertionError(f'frame 0 should be unaired before sync: {missing!r}')
            # The studio is offline; the playout frame clock keeps running on silence.
            for show in ('early', 'late'):
                frame_one = operator.tick(1, show)
                if frame_one != {'show': show, 'frame': 1, 'left': 0, 'right': 0, 'request_id': None}:
                    raise AssertionError(f'frame 1 should be silence, got {frame_one!r}')
        # Both ends reopen on their original databases.
        with running_endpoint(*playout_command) as playout, forwarding(playout.port) as proxy:
            operator = StudioClient(proxy.server_port)
            with running_endpoint(*studio_command(proxy.address)) as studio:
                for show, cue in cues.items():
                    if studio.stop(cue, show) != {'cue_id': cue, 'stopped': True}:
                        raise AssertionError(f'could not stop the original cue on {show}')
                # The original request and tick reclaim the first results after the restart.
                reclaimed = studio.stage(0, 'opening-0', 'early')
                if reclaimed != {'show': 'early', 'frame': 0, 'request_id': 'opening-0',
                                 'status': 'accepted'}:
                    raise AssertionError(f'reclaim should be accepted, got {reclaimed!r}')
                early_air = operator.tick(0, 'early')
                if early_air != {'show': 'early', 'frame': 0, 'left': 8, 'right': 0,
                                 'request_id': 'opening-0'}:
                    raise AssertionError(f'reclaimed tick should air (8, 0), got {early_air!r}')
                for show in ('early', 'late'):
                    first = studio.sync(show)
                    again = studio.sync(show)
                    if first != {'show': show, 'last_frame': 1} or again != first:
                        raise AssertionError(f'{show}: sync should reach frame 1 and stay, '
                                             f'got {first!r} then {again!r}')
                early_replay = studio.replay(0, 1, 'early')
                late_replay = studio.replay(0, 1, 'late')
                expected_early = [
                    {'show': 'early', 'frame': 0, 'left': 8, 'right': 0, 'request_id': 'opening-0'},
                    {'show': 'early', 'frame': 1, 'left': 0, 'right': 0, 'request_id': None},
                ]
                expected_late = [
                    {'show': 'late', 'frame': 0, 'left': 0, 'right': 0, 'request_id': None},
                    {'show': 'late', 'frame': 1, 'left': 0, 'right': 0, 'request_id': None},
                ]
                if early_replay != expected_early or late_replay != expected_late:
                    raise AssertionError(f'replay mismatch: {early_replay!r} / {late_replay!r}')
                if studio.read(0, 'early') != expected_early[0]:
                    raise AssertionError('relayed frame 0 lookup mismatch')
                print(f'relay early aired {early_air!r}; studio replays {early_replay!r}')
                print(f'relay late aired {late_air!r}; studio replays {late_replay!r}')
                evidence = {
                    'case_id': 'R1',
                    'input': {'shows': ['early', 'late'], 'A': {'sample': 8, 'dry_frame': 0,
                              'output': 'left'}, 'scene': {'echo_output': 'right', 'echo_delay': 2},
                              'early': 'candidate then tick, both replies dropped, studio restart',
                              'late': 'tick then candidate'},
                    'expected': {'early': expected_early, 'late': expected_late},
                    'actual': {'early': early_replay, 'late': late_replay},
                    'downstream_expected': {'early_frame0': expected_early[0]},
                    'downstream_actual': {'early_frame0': studio.read(0, 'early')},
                    'code_paths': ['mix/service.py', 'relay/client.py', 'relay/store.py',
                                   'playout/service.py', 'aircheck/record.py'],
                    'oracle': 'Candidate-first airs (8,0) under opening-0; tick-first airs silence '
                              'with a null request_id and the late candidate expires. Frame 1 is '
                              'silence on both. After dropped replies and a double restart, the '
                              'original request and tick reclaim (8,0), and sync archives the '
                              'contiguous prefix through frame 1 exactly once.',
                }
                print('POINTWISE_SCENARIO ' + json.dumps(evidence, ensure_ascii=False,
                                                          separators=(',', ':')))


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
    relay_demo()


if __name__ == '__main__':
    main()
