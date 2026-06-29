import { describe, expect, test } from 'vitest'
import type { Company } from '../api'
import {
  fmtWow,
  caretFor,
  accentFor,
  velocityWidth,
  timeLabel,
  fmtDate,
  fmtHeaderDateTime,
  sortCompanies,
  sparkline,
  ACCENT_ACCEL,
  ACCENT_COOL,
} from './encoding'

describe('fmtWow', () => {
  test('positive uses a plus and one decimal', () => {
    expect(fmtWow(120.5)).toBe('+120.5%')
  })
  test('negative uses the U+2212 minus glyph', () => {
    expect(fmtWow(-18.6)).toBe('−18.6%')
  })
  test('zero is treated as non-negative', () => {
    expect(fmtWow(0)).toBe('+0.0%')
  })
})

describe('caretFor / accentFor', () => {
  test('accelerating is a right caret and amber', () => {
    expect(caretFor(5)).toBe('▶')
    expect(accentFor(5)).toBe(ACCENT_ACCEL)
  })
  test('cooling is a left caret and blue', () => {
    expect(caretFor(-5)).toBe('◀')
    expect(accentFor(-5)).toBe(ACCENT_COOL)
  })
})

describe('velocityWidth', () => {
  test('scales |wow| against a 130 ceiling', () => {
    expect(velocityWidth(65)).toBe('50%')
  })
  test('caps at 96% so the puck never leaves the lane', () => {
    expect(velocityWidth(130)).toBe('96%')
    expect(velocityWidth(400)).toBe('96%')
  })
  test('uses magnitude, so cooling fills too', () => {
    expect(velocityWidth(-65)).toBe('50%')
  })
})

describe('timeLabel', () => {
  const generated = '2026-06-28T08:00:00+00:00'
  test('under an hour reads "now"', () => {
    expect(timeLabel('2026-06-28T07:30:00+00:00', generated)).toBe('now')
  })
  test('within a day reads hours', () => {
    expect(timeLabel('2026-06-28T05:00:00+00:00', generated)).toBe('3h ago')
  })
  test('beyond a day reads days', () => {
    expect(timeLabel('2026-06-27T05:00:00+00:00', generated)).toBe('1d ago')
  })
})

describe('fmtDate', () => {
  test('formats an ISO date as "Mon DD" in UTC', () => {
    expect(fmtDate('2026-06-25T12:00:00+00:00')).toBe('Jun 25')
  })
})

describe('fmtHeaderDateTime', () => {
  test('formats as "DD MON YYYY · HH:MM UTC" in UTC', () => {
    expect(fmtHeaderDateTime('2026-06-28T08:00:00+00:00')).toBe('28 JUN 2026 · 08:00 UTC')
  })
  test('zero-pads day and time', () => {
    expect(fmtHeaderDateTime('2026-01-05T09:07:00+00:00')).toBe('05 JAN 2026 · 09:07 UTC')
  })
})

describe('sortCompanies', () => {
  const co = (
    name: string,
    mentions: number,
    avg_importance: number | null,
    avg_sentiment: Company['avg_sentiment'],
  ): Company => ({ name, ticker: name, mentions, avg_importance, avg_sentiment })

  const companies = [
    co('A', 3, 6, 'negative'),
    co('B', 9, 8, 'neutral'),
    co('C', 5, 7, 'positive'),
    co('D', 5, 9, 'positive'),
  ]

  test('by importance, descending', () => {
    expect(sortCompanies(companies, 'importance').map((c) => c.name)).toEqual([
      'D',
      'B',
      'C',
      'A',
    ])
  })

  test('by mentions, descending', () => {
    expect(sortCompanies(companies, 'mentions').map((c) => c.name)).toEqual([
      'B',
      'C',
      'D',
      'A',
    ])
  })

  test('by sentiment: positive → neutral → negative, importance breaks ties', () => {
    expect(sortCompanies(companies, 'sentiment').map((c) => c.name)).toEqual([
      'D',
      'C',
      'B',
      'A',
    ])
  })

  test('does not mutate the input', () => {
    const input = [...companies]
    sortCompanies(input, 'mentions')
    expect(input.map((c) => c.name)).toEqual(['A', 'B', 'C', 'D'])
  })
})

describe('sparkline', () => {
  test('returns 7 points with the head at the last one', () => {
    const { points, head } = sparkline(60, 3, 240, 58)
    const coords = points.split(' ')
    expect(coords).toHaveLength(7)
    const [hx, hy] = coords[6].split(',').map(Number)
    expect(head[0]).toBeCloseTo(hx, 1)
    expect(head[1]).toBeCloseTo(hy, 1)
  })
})
