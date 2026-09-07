export function serializeCommand(argv) {
  if (!Array.isArray(argv) || !argv.length || argv.some(arg => typeof arg !== 'string' || arg.includes('\0'))) {
    throw new Error('No valid recorded command available');
  }
  return argv.map(arg => `'${arg.replaceAll("'", "'\"'\"'")}'`).join(' ');
}
