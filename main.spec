# -*- mode: python -*-
a = Analysis(['main.py'],
             pathex=['I:\\Users\\Chase Stevens\\Documents\\GitHub\\chasejellison_wiki_scraper'],
             hiddenimports=[],
             hookspath=None,
             runtime_hooks=None)
a.datas += [('phantomjs.exe', 'phantomjs.exe', 'DATA')]
pyz = PYZ(a.pure)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          name='upload_wiki.exe',
          debug=False,
          strip=None,
          upx=True,
          console=True )
