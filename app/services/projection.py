"""Server-side equivalent of machining form calcT/nct/cap; never used by PPT."""
from copy import deepcopy
import math


def _machine_for(process, machines):
    """Resolve a process machine: stable ``mid`` first, legacy ``mi`` index second."""
    reference = str(process.get('mid') or '').strip()
    if reference:
        for machine in machines:
            if str(machine.get('id') or '') == reference:
                return machine
        # 设备可能已被删除：继续按兜底机型处理，而不是静默换用别的设备。
        for machine in machines:
            if machine.get('is_fallback'):
                return machine
    try:
        index = int(float(process.get('mi')))
    except (TypeError, ValueError):
        index = -1
    if 0 <= index < len(machines):
        return machines[index]
    return machines[-1] if machines else {}


def report_runtime(state):
    state = deepcopy(state)
    machines, processes, general = state.get('mdb', []), state.get('pr', []), state.get('G', {})
    summaries = []
    def number(value):
        try:
            result = float(value or 0)
            return result if math.isfinite(result) else 0
        except (ValueError, TypeError):
            return 0
    seconds = number(general.get('hpd')) * 3600 * number(general.get('dpm')) * number(general.get('avl'))
    for process in processes:
        machine = _machine_for(process, machines)
        rapid = number(machine.get('rapid')) * 1000 / 60
        rapid = rapid if rapid > 0 else 500
        change = number(machine.get('tc'))
        nc = process.get('nc') or dict(cc=2, co=2, mc_=2, sc=2, ac=1, it=5)
        noncut = sum(number(nc.get(k)) for k in ('cc','co','mc_','sc','ac')) + number(nc.get('it') or 5)
        cut = 0
        for tool in process.get('tl', []):
            n, vf = number(tool.get('n')), number(tool.get('vf'))
            tool['_ct'] = number(tool.get('ln')) / vf * 60 * number(tool.get('ps')) * number(tool.get('cn')) if vf > 0 else 0
            tool['_vc'] = math.floor(math.pi * number(tool.get('d')) * n / 1000 + .5)
            tool['_vf'], tool['_fz'] = vf, vf/n if n > 0 else 0
            cut += tool['_ct']
            noncut += number(tool.get('td') or 500)/rapid + change*(2 if tool.get('bg') else 1) + number(tool.get('tt') or 2) + number(tool.get('sd') or 1)
        cycle = cut + noncut
        summaries.append(dict(name=process.get('nm',''), cut_seconds=cut, noncut_seconds=noncut,
                              cycle_seconds=cycle, monthly_capacity=seconds/cycle*number(process.get('mc')) if cycle > 0 else 0))
    return {'adapter': 'dfm_quote_v1', 'state': state, 'computed': {
        'processes': summaries, 'total_seconds': sum(p['cycle_seconds'] for p in summaries),
        'monthly_capacity': min((p['monthly_capacity'] for p in summaries), default=0)}}
