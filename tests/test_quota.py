import copy
import time
import unittest
from unittest.mock import Mock, patch

from shorekeeper_pet.quota import quota_from_limits, quota_view, quota_label, quota_details, format_credits, refresh_seconds
from shorekeeper_pet.bridge import RateClient, SessionReader


def payload(used=100, balance='1234.5678', **overrides):
    bucket = dict(limitId='codex', primary=dict(usedPercent=used, windowDurationMins=10080, resetsAt=1800000000),
                  credits=dict(hasCredits=True, unlimited=False, balance=balance), spendControlReached=False)
    bucket.update(overrides)
    return dict(rateLimits=bucket, rateLimitsByLimitId={'codex': bucket})


def normalized(**kwargs):
    return dict(quota_from_limits(payload(**kwargs)), source='live', updated_at=time.time(), error=None)


class CreditQuotaTests(unittest.TestCase):
    def test_plan_uses_its_own_remaining_percent_even_with_credits(self):
        view = quota_view(normalized(used=25))
        self.assertEqual((view.mode, view.label, view.remaining), ('plan', '套餐剩余：75%', 75))

    def test_exhausted_plan_shows_changing_balance_without_percentage(self):
        before, after = normalized(), normalized(balance='1201.1234')
        self.assertEqual(quota_label(before), '超限代偿：1,234.56')
        self.assertEqual(quota_label(after), '超限代偿：1,201.12')
        self.assertIsNone(quota_view(after).remaining)
        self.assertIn('1,201.1234 credits', quota_details(after))
        self.assertIn('重置', quota_details(after))

    def test_reset_returns_to_included_usage(self):
        self.assertEqual(quota_view(normalized()).mode, 'credits')
        self.assertEqual(quota_view(normalized(used=0)).label, '套餐剩余：100%')

    def test_short_window_can_exhaust_before_weekly(self):
        data = payload(used=15)
        data['rateLimits']['secondary'] = dict(usedPercent=100, windowDurationMins=300)
        self.assertEqual(quota_view(quota_from_limits(data)).mode, 'credits')

    def test_other_bucket_exhaustion_does_not_override_codex(self):
        data = payload(used=25)
        data['rateLimitsByLimitId']['review'] = dict(primary=dict(usedPercent=100), credits=dict(balance='99999'))
        view = quota_view(quota_from_limits(data))
        self.assertEqual((view.bucket, view.mode, view.remaining), ('codex', 'plan', 75))

    def test_no_codex_bucket_does_not_mix_unrelated_balances(self):
        data = quota_from_limits(dict(rateLimitsByLimitId={'a':dict(credits=dict(balance='10')), 'b':dict(credits=dict(balance='20'))}))
        self.assertEqual(quota_view(data).mode, 'unknown')

    def test_credits_only_accounts_do_not_need_a_percentage_window(self):
        data = normalized(primary=None)
        self.assertEqual(quota_view(data).mode, 'credits')
        self.assertEqual(data['windows'], [])

    def test_missing_credits_is_unknown_not_zero(self):
        view = quota_view(normalized(credits=None))
        self.assertEqual(view.label, '套餐额度已用完')
        self.assertIn('未返回', quota_details(normalized(credits=None)))
        self.assertEqual(quota_view(normalized(balance=None)).label, '超限代偿：未知')

    def test_unlimited_credits_do_not_mean_unlimited_plan(self):
        data = normalized(credits=dict(hasCredits=True, unlimited=True, balance=None))
        self.assertEqual(quota_view(data).label, '超限代偿：不限额')
        self.assertIsNone(quota_view(data).remaining)

    def test_spend_control_blocks_despite_positive_balance(self):
        self.assertEqual(quota_view(normalized(spendControlReached=True)).mode, 'blocked')
        self.assertIn('有余额也不代表', quota_details(normalized(spendControlReached=True)))

    def test_zero_balance_and_recharge(self):
        self.assertEqual(quota_view(normalized(balance='0')).mode, 'depleted')
        self.assertEqual(quota_view(normalized(balance='0')).label, '超限代偿：0')
        self.assertEqual(quota_view(normalized(balance='10')).mode, 'credits')

    def test_has_no_credits_flag_is_respected(self):
        data = normalized(credits=dict(hasCredits=False, unlimited=False, balance='100'))
        self.assertEqual(quota_view(data).mode, 'depleted')

    def test_credit_decimal_is_not_rounded_up_or_converted_to_currency(self):
        self.assertEqual(format_credits('1.99999', True), '1.99')
        self.assertEqual(format_credits('0.00001', True), '<0.01')
        self.assertEqual(format_credits('1000.0000000000'), '1,000')
        for value in (True, 'NaN', 'Infinity', '-2', None, {}, 'bad', '1e30'):
            self.assertEqual(format_credits(value), '未知')

    def test_bad_windows_and_missing_data_are_not_zero(self):
        for value in (True, float('nan'), float('inf'), None, '100'):
            self.assertEqual(quota_from_limits(payload(used=value))['windows'], [])
        self.assertEqual(quota_view({}).label, '额度：--')

    def test_legacy_camel_and_snake_credit_fields(self):
        camel = payload()['rateLimits']
        snake = dict(limit_id='codex', primary=dict(used_percent=100, window_minutes=10080),
                     credits=dict(has_credits=True, balance='1234.5678'))
        for item in (camel, snake):
            self.assertEqual(quota_view(quota_from_limits({'rateLimits':item})).label, '超限代偿：1,234.56')

    def test_legacy_view_can_supply_missing_same_bucket_metadata(self):
        data = payload()
        data['rateLimitsByLimitId'] = {'codex':dict(primary=data['rateLimits']['primary'])}
        self.assertEqual(quota_view(quota_from_limits(data)).mode, 'credits')

    def test_stale_and_failed_queries_keep_balance_but_mark_cached(self):
        data = normalized()
        self.assertNotIn('*', quota_label(data, True))
        for change in ({'error':'offline'}, {'source':'session'}, {'updated_at':time.time()-301}):
            self.assertTrue(quota_label(dict(data, **change), True).endswith(' *'))

    def test_refresh_credits_faster_than_plan(self):
        self.assertEqual(refresh_seconds(normalized()), 30)
        self.assertEqual(refresh_seconds(normalized(balance='0')), 30)
        self.assertEqual(refresh_seconds(normalized(used=5)), 120)

    def test_live_client_preserves_credits_without_requesting_inference(self):
        client = RateClient()
        client.process = Mock(); client.process.poll.return_value = None
        with patch.object(client, '_send') as send, patch.object(client, '_response', return_value=payload()):
            data = client.read()
        self.assertEqual(send.call_args.args[0]['method'], 'account/rateLimits/read')
        self.assertEqual(quota_view(data).mode, 'credits')

    def test_session_cache_preserves_credit_fields(self):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.jsonl'
            path.write_text(json.dumps(dict(timestamp='2026-10-18T12:00:00Z', type='event_msg', payload=dict(type='token_count', rate_limits=payload()['rateLimits'])))+'\n')
            data = SessionReader(path).rate
            self.assertEqual(quota_view(data).mode, 'credits')
            self.assertIn('缓存', quota_label(data))

    def test_new_missing_balance_clears_previous_balance(self):
        from shorekeeper_pet.pet import Pet
        pet = Mock(); pet.quota_data = normalized(); pet.panel = None
        empty = normalized(credits=None); empty['updated_at'] += 1
        Pet.on_quota(pet, empty)
        self.assertEqual(quota_view(pet.quota_data).label, '套餐额度已用完')
        older = normalized(); older['updated_at'] = empty['updated_at']-5
        Pet.on_quota(pet, older)
        self.assertEqual(pet.quota_data, empty)


if __name__ == '__main__':
    unittest.main()
