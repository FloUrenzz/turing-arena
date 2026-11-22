import sqlite3
from pathlib import Path

DB = Path(__file__).parent / 'data' / 'demo.sqlite3'


def seed(path=DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript('''
    CREATE TABLE IF NOT EXISTS concepts(id TEXT PRIMARY KEY, lemma TEXT, acc TEXT, gender TEXT, definition TEXT);
    CREATE TABLE IF NOT EXISTS forms(form TEXT PRIMARY KEY, concept TEXT, pos TEXT, features TEXT);
    CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY, subject TEXT, predicate TEXT, object TEXT, value REAL, reason TEXT);
    ''')
    words = [
        ('tea','чай','чай','m','Напиток из заваренных чайных листьев.','чай чая чаю чаем чае чаек чаёк'),
        ('coffee','кофе','кофе','m','Напиток из обжаренных кофейных зёрен.','кофе кофейку кофеек кофеёк'),
        ('music','музыка','музыку','f','Искусство, в котором основным материалом служит звук.','музыка музыку музыке музыкой музыки'),
        ('programming','программирование','программирование','n','Создание программ для компьютера.','программирование программирования программированием кодить код программировать'),
        ('early_rising','ранний подъём','ранний подъём','m','Пробуждение рано утром.','подъем подъём вставать просыпаться рано'),
        ('book','книга','книгу','f','Записанное произведение, обычно изданное на страницах.','книга книги книгу книгой книжки читать чтение'),
        ('sleep','сон','сон','m','Состояние отдыха организма.','сон сна спать сном'),
        ('study','учёба','учёбу','f','Получение знаний и навыков.','учеба учёба учебу учёбу учиться учебе учёбе пары'),
        ('friend','друг','друга','m','Человек, с которым связывают близкие отношения.','друг друга друзья друзей дружба'),
        ('rain','дождь','дождь','m','Осадки в виде капель воды.','дождь дождя дождем дождём'),
        ('film','фильм','фильм','m','Произведение, записанное как движущиеся изображения.','фильм фильма фильмы кино'),
        ('walk','прогулка','прогулку','f','Неторопливая ходьба для отдыха.','прогулка прогулку прогулки гулять'),
        ('sport','спорт','спорт','m','Занятия физическими упражнениями и соревнования.','спорт спорта спортом'),
        ('pizza','пицца','пиццу','f','Открытая лепёшка с начинкой.','пицца пиццу пиццы'),
        ('cat','кошка','кошку','f','Домашнее животное семейства кошачьих.','кошка кошку кошки кот кота'),
        ('dog','собака','собаку','f','Домашнее животное семейства псовых.','собака собаку собаки пес пёс'),
        ('winter','зима','зиму','f','Холодное время года.','зима зиму зимой'),
        ('summer','лето','лето','n','Тёплое время года.','лето лета летом'),
        ('water','вода','воду','f','Жидкость, необходимая для жизни.','вода воду воды'),
        ('food','еда','еду','f','То, что едят.','еда еду еды есть кушать'),
    ]
    for cid, lemma, acc, gender, definition, forms in words:
        con.execute('INSERT OR REPLACE INTO concepts VALUES(?,?,?,?,?)',(cid,lemma,acc,gender,definition))
        for form in forms.split():
            con.execute('INSERT OR REPLACE INTO forms VALUES(?,?,?,?)',(form.replace('ё','е'),cid,'noun','demo'))
    facts = [('likes_tea','self','likes','tea',2,'С ним уютнее сидеть вечером.'),
             ('likes_coffee','self','likes','coffee',-1,'Мне не очень нравится его горечь.'),
             ('likes_music','self','likes','music',2,'Так легче отвлечься после учёбы.'),
             ('likes_programming','self','likes','programming',2,'Мне нравится разбираться, как всё устроено.'),
             ('dislikes_early_rising','self','likes','early_rising',-2,'По утрам мне тяжело проснуться.'),
             ('name','self','name','Саша',0,''),('student','self','role','студент',0,'Сейчас учусь.'),
             ('likes_book','self','likes','book',1,'Можно ненадолго отвлечься.'),
             ('likes_walk','self','likes','walk',1,'После неё голова яснее.')]
    con.executemany('INSERT OR REPLACE INTO facts VALUES(?,?,?,?,?,?)',facts)
    con.commit()
    con.close()
    return path


if __name__ == '__main__':
    print(seed())
