/**
 * Catalog dates read as times, the way the Data Catalog's listing reads them
 * (``datasets/domain/catalog_dates.py``): dates written to the second, the
 * millisecond or the microsecond, with ``Z`` or an offset, compare by when
 * they are. A date without an offset is UTC. A missing date, or one that does
 * not read as a date, is the oldest.
 *
 * A date reads in the ISO 8601 extended form: ``YYYY-MM-DD``, optionally
 * followed, after ``T`` or a space, by ``HH:MM`` or ``HH:MM:SS`` with a
 * fraction (``.`` or ``,``), and ``Z`` or an offset (``+HH:MM``, ``+HHMM`` or
 * ``+HH``). ``catalogDates.cases.json`` beside it holds the cases both run.
 */

const CATALOG_DATE =
  /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?(Z|[+-]\d{2}(?::?\d{2})?)?)?$/;

/** Whole seconds since 1970-01-01T00:00:00Z, and the microseconds past them. */
type Moment = readonly [number, number];

const SECONDS_PER_DAY = 86400;

/** Days from 1970-01-01 to a day of the (proleptic) Gregorian calendar. */
function daysFromCivil(year: number, month: number, day: number): number {
  const y = month <= 2 ? year - 1 : year;
  const era = Math.floor(y / 400);
  const yearOfEra = y - era * 400;
  const dayOfYear = Math.floor((153 * ((month + 9) % 12) + 2) / 5) + day - 1;
  const dayOfEra =
    yearOfEra * 365 + Math.floor(yearOfEra / 4) - Math.floor(yearOfEra / 100) + dayOfYear;
  return era * 146097 + dayOfEra - 719468;
}

function daysInMonth(year: number, month: number): number {
  if (month === 2) {
    return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0 ? 29 : 28;
  }
  return month === 4 || month === 6 || month === 9 || month === 11 ? 30 : 31;
}

/** 0001-01-01T00:00:00Z, the oldest date the listing reads (``OLDEST``). */
const OLDEST: Moment = [daysFromCivil(1, 1, 1) * SECONDS_PER_DAY, 0];

function readCatalogDate(stamp: string | null | undefined): Moment {
  const match = typeof stamp === "string" ? CATALOG_DATE.exec(stamp.trim()) : null;
  if (!match) return OLDEST;
  const [, y, mo, d, h = "0", mi = "0", s = "0", fraction = "", offset = "Z"] = match;
  const [year, month, day] = [Number(y), Number(mo), Number(d)];
  const [hour, minute, second] = [Number(h), Number(mi), Number(s)];
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) {
    return OLDEST;
  }
  if (hour > 23 || minute > 59 || second > 59) return OLDEST;
  let offsetSeconds = 0;
  if (offset !== "Z") {
    const digits = offset.slice(1).replace(":", "");
    const [offsetHours, offsetMinutes] = [Number(digits.slice(0, 2)), Number(digits.slice(2) || 0)];
    if (offsetHours > 23 || offsetMinutes > 59) return OLDEST;
    offsetSeconds = (offset[0] === "-" ? -1 : 1) * (offsetHours * 3600 + offsetMinutes * 60);
  }
  const seconds =
    daysFromCivil(year, month, day) * SECONDS_PER_DAY +
    hour * 3600 +
    minute * 60 +
    second -
    offsetSeconds;
  // To the microsecond: digits past the sixth are dropped.
  return [seconds, Number(fraction.slice(0, 6).padEnd(6, "0"))];
}

/**
 * Compare two catalog dates as times: negative when ``a`` is the older,
 * positive when it is the newer, 0 when both are the same time.
 */
export function compareCatalogDates(
  a: string | null | undefined,
  b: string | null | undefined,
): number {
  const [aSeconds, aMicros] = readCatalogDate(a);
  const [bSeconds, bMicros] = readCatalogDate(b);
  return aSeconds - bSeconds || aMicros - bMicros;
}
