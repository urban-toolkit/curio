import fs from "fs";
import path from "path";

/**
 * The review card's text has no en or em dashes. #512 took them out of the
 * Solve row and the builder strip; the card kept about two dozen ("Applying
 * adds these 6 connected nodes to the canvas" and its siblings, the status
 * chips, the removal and permission lines). Each became a colon, a comma, a
 * semicolon or parentheses.
 *
 * Read from the source: the strings are spread across maps, template literals
 * and JSX text, and a render would only cover the branches a fixture reaches.
 * The card is AgentReviewCard.tsx plus the pieces under reviewCard/.
 */
const CONTENT = path.resolve(__dirname, "../../components/agents/content");
const PIECES = fs
  .readdirSync(path.join(CONTENT, "reviewCard"))
  .filter((name) => /\.tsx?$/.test(name))
  .map((name) => path.join("reviewCard", name));
const CARD = ["AgentReviewCard.tsx", ...PIECES].map((file) => ({
  file,
  text: fs.readFileSync(path.join(CONTENT, file), "utf8"),
}));

test("no string or JSX text in the card carries an en or em dash", () => {
  const offenders = CARD.flatMap(({ file, text }) =>
    text
      .split("\n")
      .map((line, index) => ({ line, number: index + 1 }))
      .filter(({ line }) => /[–—]/.test(line))
      .filter(({ line }) => {
        const trimmed = line.trim();
        // Comments may keep them; the reader never sees a comment.
        return !(trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("/*") || trimmed.startsWith("{/*"));
      })
      .map(({ line, number }) => `${file}:${number}: ${line.trim()}`),
  );
  expect(offenders).toEqual([]);
});
