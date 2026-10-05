/** `1 node`, `2 nodes`: a count and its noun, agreeing (#508). */
export function countLabel(n: number, noun: string, plural: string = `${noun}s`): string {
  return `${n} ${n === 1 ? noun : plural}`;
}
