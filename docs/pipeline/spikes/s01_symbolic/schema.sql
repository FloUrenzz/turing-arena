CREATE TABLE concepts(id TEXT PRIMARY KEY, lemma TEXT, acc TEXT, gender TEXT, definition TEXT);

CREATE TABLE facts(id TEXT PRIMARY KEY, subject TEXT, predicate TEXT, object TEXT, value REAL, reason TEXT);

CREATE TABLE forms(form TEXT PRIMARY KEY, concept TEXT, pos TEXT, features TEXT);

CREATE TABLE groups(concept TEXT, category TEXT, PRIMARY KEY(concept,category));
