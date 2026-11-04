import unittest
from work_desktop import Box,CHORDS,KEYS,DENIED
class DesktopBoundsTests(unittest.TestCase):
    def test_coordinates(self):
        b=Box(100,200,500,400)
        self.assertEqual(b.point(12,13),(112,213))
        for x,y in [(-1,0),(500,1),(1,400),(True,1),(1.5,1)]:
            with self.assertRaises(ValueError):b.point(x,y)
    def test_no_execution_shortcuts(self):
        self.assertNotIn(('win','r'),CHORDS)
        self.assertNotIn('win',KEYS)
        self.assertIn('powershell.exe',DENIED)
if __name__=='__main__':unittest.main()
