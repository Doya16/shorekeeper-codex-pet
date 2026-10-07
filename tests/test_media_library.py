import json,pathlib,tempfile,unittest
from PIL import Image
from shorekeeper_pet.media_library import load_catalog,import_images
from shorekeeper_pet.config_io import export_bundle,import_bundle
from shorekeeper_pet.bindings import BindingMap
from shorekeeper_pet.presets import load_defaults,default_bindings

class MediaLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=pathlib.Path(self.temp.name)/'pet'; (self.root/'assets').mkdir(parents=True)
        (self.root/'assets/catalog.json').write_text('[]'); self.source=self.root.parent/'incoming'; self.source.mkdir()
    def tearDown(self): self.temp.cleanup()
    def test_import_preview_metadata_all_formats_and_stable_id(self):
        first=Image.new('RGB',(60,40),'blue'); second=Image.new('RGB',(60,40),'white')
        for ext in ('png','jpg','jpeg'): first.save(self.source/('picture.'+ext))
        for ext in ('gif','webp'): first.save(self.source/('animation.'+ext),save_all=True,append_images=[second],duration=[100,200],loop=0)
        paths,warnings=import_images(list(self.source.iterdir()),self.root); self.assertFalse(warnings); self.assertEqual(len(paths),5)
        catalog,warnings=load_catalog(self.root); self.assertFalse(warnings); self.assertEqual(len(catalog),5)
        self.assertTrue(all(row['frames']==2 for row in catalog if row['name'].startswith('animation')))
        before={row['name']:row['id'] for row in catalog}
        first.save(self.root/'assets/custom/picture.png')
        self.assertEqual(before,{row['name']:row['id'] for row in load_catalog(self.root)[0]})
    def test_corrupt_and_unsupported_files_are_not_selectable(self):
        (self.source/'bad.gif').write_bytes(b'not a gif'); (self.source/'not-an-image.txt').write_text('data')
        paths,warnings=import_images(list(self.source.iterdir()),self.root)
        self.assertFalse(paths); self.assertEqual(len(warnings),2)
        self.assertEqual(load_catalog(self.root)[0],[])
    def test_import_does_not_overwrite_same_name(self):
        path=self.source/'same.png'; Image.new('RGB',(10,10),'blue').save(path)
        original=import_images([path],self.root)[0][0]; before=original.read_bytes()
        Image.new('RGB',(10,10),'red').save(path)
        changed=import_images([path],self.root)[0][0]
        self.assertNotEqual(original,changed); self.assertEqual(original.read_bytes(),before)
    def test_custom_images_defaults_and_audio_survive_relocation(self):
        Image.new('RGB',(15,25),'blue').save(self.source/'my.webp'); import_images([self.source/'my.webp'],self.root)
        aid=load_catalog(self.root)[0][0]['id']
        (self.root/'defaults/audio').mkdir(parents=True); (self.root/'defaults/audio/voice.wav').write_bytes(b'RIFF test')
        baseline={'scale':.85,'appearance':{'audio_directory':'defaults/audio'},'bindings':{'idle':{'asset':aid,'bubble_text':'台词','audio_clips':[{'file':'voice.wav'}]}}}
        (self.root/'defaults/settings.json').write_text(json.dumps(baseline),encoding='utf8')
        archive=self.root.parent/'profile.zip'; export_bundle(archive,baseline,self.root)
        target=self.root.parent/'moved'; cfg=import_bundle(archive,target)
        self.assertEqual(load_catalog(target)[0][0]['id'],aid)
        self.assertEqual(load_defaults(target),baseline)
        self.assertTrue(pathlib.Path(default_bindings(target)['idle']['audio_clips'][0]['file']).is_file())
        self.assertEqual(cfg['scale'],.85)
    def test_reset_restores_shipped_state_without_touching_others(self):
        b=BindingMap({'pack':{'idle':'old','pet':'old'}},['old','new'],[],{'idle':{'asset':'old'},'pet':{'speed':2}},baseline={'idle':{'asset':'new','bubble_text':'default','audio_clips':[{'file':'default.wav'}]}})
        b.reset('idle'); self.assertEqual(b.resolve('pack','idle')['asset'],'new')
        self.assertEqual(b.resolve('pack','idle')['audio_clips'][0]['file'],'default.wav')
        self.assertEqual(b.resolve('pack','pet')['speed'],2)
        b.assets={'old'}; self.assertEqual(b.resolve('pack','idle')['asset'],'old')

if __name__=='__main__': unittest.main()
