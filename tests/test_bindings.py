import json,unittest
from shorekeeper_pet.bindings import BindingMap

class BindingTests(unittest.TestCase):
    def setUp(self):
        self.defaults={'a':{'idle':'one','pet':'two','drag':'one'},'b':{'idle':'three','pet':'one','drag':'three'}}
        self.map=BindingMap(self.defaults,['one','two','three'],{'pet'})
    def test_defaults_and_single_override(self):
        self.assertEqual(self.map.resolve('a','pet')['playback'],'once')
        self.map.set('pet',asset='three',playback='loop')
        value=self.map.resolve('a','pet')
        self.assertEqual({k:value[k] for k in ('asset','playback','custom')},dict(asset='three',playback='loop',custom=True))
        self.assertEqual(self.map.resolve('a','idle')['asset'],'one')
    def test_pack_change_keeps_custom_choices(self):
        self.map.set('pet',asset='three')
        self.assertEqual(self.map.resolve('a','pet')['asset'],'three')
        self.assertEqual(self.map.resolve('b','pet')['asset'],'three')
        self.assertEqual(self.map.resolve('b','idle')['asset'],'three')
    def test_json_roundtrip_and_reset_only_one(self):
        self.map.set('pet',asset='three',playback='loop')
        self.map.set('drag',asset='two')
        restored=BindingMap(self.defaults,['one','two','three'],{'pet'},json.loads(json.dumps(self.map.to_dict())))
        self.assertEqual(restored.resolve('b','pet')['playback'],'loop')
        restored.reset('pet')
        self.assertEqual(restored.resolve('b','pet')['asset'],'one')
        self.assertEqual(restored.resolve('b','drag')['asset'],'two')
    def test_playback_only_retains_preset_art(self):
        self.map.set('idle',playback='loop')
        self.assertEqual(self.map.resolve('b','idle')['asset'],'three')
    def test_invalid_saved_entries_fall_back(self):
        restored=BindingMap(self.defaults,['one','two','three'],{'pet'},{'pet':{'asset':'missing','playback':'bad'},'unknown':{'asset':'one'},'idle':None})
        self.assertEqual(restored.resolve('a','pet')['asset'],'two')
        self.assertEqual(restored.to_dict(),{})
    def test_invalid_update_does_not_corrupt_valid_binding(self):
        self.map.set('pet',asset='three')
        with self.assertRaises(ValueError): self.map.set('pet',asset='bad')
        self.assertEqual(self.map.resolve('a','pet')['asset'],'three')

if __name__=='__main__': unittest.main()
