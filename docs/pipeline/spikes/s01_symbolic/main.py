import argparse
import json
import random
import time

from engine import Bot
from seed import DB, seed


def run():
    p = argparse.ArgumentParser(description='Исследовательский алгоритмический бот. Python stdlib, SQLite.')
    p.add_argument('--ask')
    p.add_argument('--chat', action='store_true')
    p.add_argument('--json', action='store_true')
    p.add_argument('--timed', action='store_true')
    p.add_argument('--seed', type=int)
    p.add_argument('--db', default=str(DB))
    args = p.parse_args()
    if args.db == str(DB) and not DB.exists():
        seed()
    bot = Bot(args.db)
    rng = random.Random(args.seed)
    if not args.chat and args.ask is None:
        p.error('Укажи --ask или --chat')
    while True:
        try:
            question = input('> ') if args.chat else args.ask
        except (EOFError, KeyboardInterrupt):
            break
        started = time.monotonic()
        result = bot.prepare(question)
        target = max(3, min(40, 3 + .12 * len(result['text']) + rng.uniform(-1, 1)))
        if args.timed:
            time.sleep(max(0, target - (time.monotonic() - started)))
        print(json.dumps(result, ensure_ascii=False) if args.json else result['text'], flush=True)
        bot.commit(question, result)
        if not args.chat:
            break


if __name__ == '__main__':
    run()
