"""Keep included usage windows separate from the account's credit balance."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import math
import time


def field(value, camel, snake):
    return value.get(camel, value.get(snake))


def credit_number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and 0 <= result < Decimal('1e18') else None
    except InvalidOperation:
        return None


def format_credits(value, compact=False):
    number = credit_number(value)
    if number is None:
        return '未知'
    if compact:
        if 0 < number < Decimal('.01'):
            return '<0.01'
        number = number.quantize(Decimal('.01'), rounding=ROUND_DOWN)
    result = format(number, ',f')
    return result.rstrip('0').rstrip('.') if '.' in result else result


def quota_from_limits(result):
    result = result if isinstance(result, dict) else {}
    source = field(result, 'rateLimitsByLimitId', 'rate_limits_by_limit_id')
    single = field(result, 'rateLimits', 'rate_limits')
    if not isinstance(source, dict) or not source:
        source = {(field(single, 'limitId', 'limit_id') or 'codex'): single} if isinstance(single, dict) else {}
    windows, buckets = [], []
    for key, value in source.items():
        if not isinstance(value, dict):
            continue
        # Missing metadata in a multi-bucket response may exist in its legacy view.
        fallback = single if isinstance(single, dict) and (field(single, 'limitId', 'limit_id') or 'codex') == key else {}
        bucket = {**fallback, **value}
        name = field(bucket, 'limitName', 'limit_name') or str(key)
        credits = bucket.get('credits')
        normalized = None
        if isinstance(credits, dict):
            number = credit_number(credits.get('balance'))
            has = field(credits, 'hasCredits', 'has_credits')
            normalized = dict(has_credits=has if isinstance(has, bool) else None,
                              unlimited=credits.get('unlimited') is True,
                              balance=str(number) if number is not None else None)
        buckets.append(dict(id=str(key), name=name, credits=normalized,
                            spend_control_reached=field(bucket, 'spendControlReached', 'spend_control_reached') is True,
                            limit_reached_type=field(bucket, 'rateLimitReachedType', 'rate_limit_reached_type')))
        for kind in ('primary', 'secondary'):
            window = bucket.get(kind)
            if not isinstance(window, dict):
                continue
            used = field(window, 'usedPercent', 'used_percent')
            if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used):
                continue
            minutes = field(window, 'windowDurationMins', 'window_minutes')
            minutes = minutes if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) and math.isfinite(minutes) and minutes > 0 else None
            duration = '每周' if minutes == 10080 else (f'{minutes / 60:g} 小时' if minutes and minutes % 60 == 0 else f'{minutes:g} 分钟' if minutes else '额度窗口')
            reset = field(window, 'resetsAt', 'resets_at')
            reset = reset if isinstance(reset, (int, float)) and not isinstance(reset, bool) and math.isfinite(reset) else None
            windows.append(dict(bucket=str(key), name=name, kind=kind, label=duration,
                                remaining=max(0, min(100, 100 - used)), resets_at=reset))
    allowed = field(result, 'ordinaryUsageAllowed', 'ordinary_usage_allowed')
    return dict(windows=windows, buckets=buckets,
                ordinary_usage_allowed=allowed if isinstance(allowed, bool) else None)


@dataclass(frozen=True)
class QuotaView:
    mode: str
    label: str
    remaining: float | None = None
    bucket: str | None = None


def quota_view(data):
    windows = data.get('windows') or []
    buckets = data.get('buckets') or []
    ids = {b['id'] for b in buckets} | {w['bucket'] for w in windows if w.get('bucket')}
    selected = 'codex' if 'codex' in ids else next(iter(ids)) if len(ids) == 1 else None
    if len(ids) > 1 and selected is None:
        return QuotaView('unknown', '额度：多项')
    rows = [w for w in windows if not selected or w.get('bucket') == selected]
    remaining = min((w['remaining'] for w in rows), default=None)
    bucket = next((b for b in buckets if b['id'] == selected), {})
    credits = bucket.get('credits') or {}
    balance = credit_number(credits.get('balance'))
    if bucket.get('spend_control_reached'):
        return QuotaView('blocked', '已达支出上限', bucket=selected)
    if remaining is not None and remaining > 0:
        return QuotaView('plan', f'套餐剩余：{remaining:g}%', remaining, selected)
    # No claim that an individual request was billed: this is an account balance.
    if credits.get('unlimited'):
        return QuotaView('credits', '超限代偿：不限额', bucket=selected)
    if balance is not None and credits.get('has_credits') is not False:
        return QuotaView('credits' if balance > 0 else 'depleted',
                         '超限代偿：' + format_credits(balance, True), bucket=selected)
    if credits.get('has_credits') is True:
        return QuotaView('credits', '超限代偿：未知', bucket=selected)
    if remaining == 0:
        return QuotaView('depleted', '套餐额度已用完', bucket=selected)
    if balance == 0 or credits.get('has_credits') is False:
        return QuotaView('depleted', '超限代偿：0', bucket=selected)
    return QuotaView('unknown', '额度：--', bucket=selected)


def is_cached(data, now=None):
    return bool(data.get('error') or data.get('source') != 'live' or
                (time.time() if now is None else now) - data.get('updated_at', 0) > 300)


def quota_label(data, compact=False):
    label = quota_view(data).label
    if data.get('updated_at') and is_cached(data):
        label += ' *' if compact else ' · 缓存'
    return label


def quota_details(data):
    lines = [quota_label(data)]
    for window in data.get('windows', []):
        try:
            reset = datetime.fromtimestamp(window['resets_at']).astimezone().strftime('%m/%d %H:%M') if window.get('resets_at') else '未知'
        except (ValueError, OSError, OverflowError):
            reset = '未知'
        lines.append(f"{window.get('name', 'Codex')} · {window['label']}套餐剩余 {window['remaining']:g}% · 重置 {reset}")
    for bucket in data.get('buckets', []):
        credits = bucket.get('credits')
        if credits is None:
            lines.append(f"{bucket['name']} · 超限代偿（点数余额）未返回")
        else:
            value = '不限额' if credits.get('unlimited') else format_credits(credits.get('balance'))
            if credits.get('has_credits') is False and credits.get('balance') is None:
                value = '无可用点数'
            lines.append(f"{bucket['name']} · 超限代偿（点数余额）{value} credits")
        if bucket.get('spend_control_reached'):
            lines.append('已达到支出限制；有余额也不代表当前可继续使用。')
    if quota_view(data).mode in ('credits', 'depleted'):
        lines.append('套餐额度与额外点数分别计算；点数没有固定总量，不显示百分比。')
    lines.append('credits 为用量点数，不是货币或固定任务次数；余额不表示当前请求已扣费。')
    if data.get('updated_at'):
        lines.append('最近读取：' + datetime.fromtimestamp(data['updated_at']).astimezone().strftime('%m/%d %H:%M:%S'))
    lines += ['* 表示缓存记录；点数模式约每 30 秒刷新',
              '拖动左右两侧调整大小；右键 → 刷新额度']
    return '\n'.join(lines)


def refresh_seconds(data):
    return 30 if quota_view(data).mode in ('credits', 'depleted', 'blocked') else 120
