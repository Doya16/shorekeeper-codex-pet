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
        return QuotaView('plan', f'算力配额：{remaining:g}%', remaining, selected)
    # No claim that an individual request was billed: this is an account balance.
    if credits.get('unlimited'):
        return QuotaView('credits', '超限配额：不限额', bucket=selected)
    if balance is not None and credits.get('has_credits') is not False:
        return QuotaView('credits' if balance > 0 else 'depleted',
                         '超限配额：' + format_credits(balance, True), bucket=selected)
    if credits.get('has_credits') is True:
        return QuotaView('credits', '超限配额：未知', bucket=selected)
    if remaining == 0:
        return QuotaView('depleted', '算力配额已用完', bucket=selected)
    if balance == 0 or credits.get('has_credits') is False:
        return QuotaView('depleted', '超限配额：0', bucket=selected)
    return QuotaView('unknown', '额度：--', bucket=selected)


def is_cached(data, now=None):
    return bool(data.get('error') or data.get('source') != 'live' or
                (time.time() if now is None else now) - data.get('updated_at', 0) > 300)


def quota_label(data, compact=False):
    label = quota_view(data).label
    if data.get('updated_at') and is_cached(data):
        label += ' *' if compact else ' · 缓存'
    return label


def quota_details(data, now=None):
    now = time.time() if now is None else now
    lines = []
    windows = data.get('windows') or []
    selected = quota_view(data).bucket
    windows = [w for w in windows if not selected or w.get('bucket') == selected]
    for window in windows:
        reset = window.get('resets_at')
        label = window.get('label', '额度')
        if not selected and window.get('name'):
            label = window['name'] + ' · ' + label
        try:
            if isinstance(reset, bool) or not isinstance(reset, (int, float)) or not math.isfinite(reset):
                raise ValueError('Unknown reset')
            date = datetime.fromtimestamp(reset).astimezone().strftime('%Y/%m/%d %H:%M')
            minutes = max(0, math.ceil((reset - now) / 60))
            hours, minutes = divmod(minutes, 60)
            suffix = f'（{hours}小时{minutes}分钟后）' if reset > now else '（已到刷新时间）'
            lines.append(f'{label}下次刷新：{date}{suffix}')
        except (ValueError, OSError, OverflowError):
            lines.append(f'{label}下次刷新：时间未知')
    if not windows:
        lines.append('下次刷新：时间未知')
    lines += ['*表示额度未更新', '拖动余额框修改大小', '点击余额框刷新余额']
    return '\n'.join(lines)


def refresh_seconds(data):
    return 30 if quota_view(data).mode in ('credits', 'depleted', 'blocked') else 120
