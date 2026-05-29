import pyxel

pyxel.init(300, 120, title="TEST")

def update():
    pass

def draw():
    pyxel.cls(1)

    pyxel.text(20, 20, "HELLO PYXEL", 7)
    pyxel.text(20, 40, "WEB TEST", 10)

pyxel.run(update, draw)
