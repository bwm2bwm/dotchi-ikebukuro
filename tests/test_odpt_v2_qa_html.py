"""Static HTML connection checks; no browser, source data, or network."""
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Elements(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.nodes = []
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))


class V2QaHtmlTests(unittest.TestCase):
    def setUp(self):
        self.nodes = Elements((ROOT / '_local_preview/odpt_v2_qa.html').read_text()).nodes
        self.by_id = {attrs['id']: (tag, attrs) for tag, attrs in self.nodes if 'id' in attrs}

    def test_entry_required_ids_are_unique_and_present_with_correct_tags(self):
        entry = (ROOT / '_local_preview/preview_odpt_v2_qa.mjs').read_text()
        ids = re.findall(r"'([^']+)'", re.search(r'const IDS = \[(.*?)\];', entry, re.S)[1])
        all_ids = [a['id'] for _, a in self.nodes if 'id' in a]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        for name in ids:
            self.assertIn(name, self.by_id)
        expected = {'clock': 'time', 'qa-datetime': 'input', 'direct-only': 'input',
                    'destination-dialog': 'dialog', 'destination-list': 'ul', 'board': 'div',
                    'route-display': 'span', 'qa-generated-at': 'p'}
        expected.update({name: 'button' for name in ('qa-clock-set', 'qa-clock-real',
            'destination-trigger', 'destination-close', 'mode-line', 'mode-departure')})
        for name, tag in expected.items():
            self.assertEqual(self.by_id[name][0], tag, name)

    def test_default_controls_status_and_dialog_references(self):
        attrs = lambda name: self.by_id[name][1]
        self.assertEqual(attrs('qa-datetime')['type'], 'datetime-local')
        self.assertEqual(attrs('qa-datetime')['step'], '1')
        self.assertEqual(attrs('direct-only')['type'], 'checkbox')
        self.assertNotIn('checked', attrs('direct-only'))
        for name, pressed in [('mode-line', 'false'), ('mode-departure', 'true')]:
            self.assertEqual(attrs(name)['aria-pressed'], pressed)
            self.assertEqual('sel' in attrs(name).get('class', '').split(), pressed == 'true')
        self.assertEqual(attrs('board')['aria-live'], 'off')
        self.assertEqual(attrs('timetable-status')['role'], 'status')
        self.assertEqual(attrs('timetable-status')['aria-live'], 'polite')
        self.assertEqual(attrs('route-coverage')['aria-live'], 'polite')
        self.assertEqual(attrs('destination-trigger')['aria-controls'], 'destination-dialog')
        self.assertIn(attrs('destination-dialog')['aria-labelledby'], self.by_id)
        self.assertTrue(any(tag == 'label' and a.get('for') == 'qa-datetime' for tag, a in self.nodes))

    def test_module_and_stylesheet_paths(self):
        scripts = [a for tag, a in self.nodes if tag == 'script']
        self.assertEqual(scripts, [{'type': 'module', 'src': 'preview_odpt_v2_qa.mjs'}])
        links = [a['href'] for tag, a in self.nodes if tag == 'link' and a.get('rel') == 'stylesheet']
        self.assertEqual(links, ['styles.css', 'preview.css', 'odpt_v2_qa.css'])
        # styles.css is copied from root by the existing QA preparer.
        self.assertTrue((ROOT / 'styles.css').is_file())
        for name in links[1:] + [scripts[0]['src']]:
            self.assertTrue((ROOT / '_local_preview' / name).is_file())
