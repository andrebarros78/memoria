import psycopg

q="select tablename from pg_tables where schemaname='public' order by tablename"
with psycopg.connect('postgresql://postgres@127.0.0.1:55439/memory_recovery') as c:a={r[0] for r in c.execute(q).fetchall()}
with psycopg.connect('postgresql://postgres@127.0.0.1:55439/memory_restore_p18') as c:b={r[0] for r in c.execute(q).fetchall()}
print('src',len(a),'dst',len(b));print('missing',sorted(a-b));print('extra',sorted(b-a))