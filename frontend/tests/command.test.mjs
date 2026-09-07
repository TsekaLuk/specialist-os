import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import test from 'node:test';
import { serializeCommand } from '../src/lib/command.mjs';

test('POSIX shell preserves every argument literally', () => {
  const args = ['', '/tmp/music files/song.wav', '{"no_cache":true}', "a'b", '$HOME', '$(false)', '`false`', 'line\nbreak', '中文'];
  const output = execFileSync('/bin/sh', ['-c', serializeCommand(['printf', '%s\\0', ...args])]);
  assert.deepEqual(output.toString().split('\0').slice(0, -1), args);
});

test('missing and invalid commands cannot report successful copying', () => {
  for (const value of [undefined, [], ['a\0b'], [3]]) {
    assert.throws(() => serializeCommand(value));
  }
});
