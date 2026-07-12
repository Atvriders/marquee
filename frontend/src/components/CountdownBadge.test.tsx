import { render, screen } from "@testing-library/react";
import { CountdownBadge, daysUntil } from "./CountdownBadge";

const NOW = new Date("2026-07-11T00:00:00Z");

test("daysUntil rounds up future dates", () => {
  expect(daysUntil("2026-08-22T00:00:00Z", NOW)).toBe(42);
});

test("daysUntil returns null for null/invalid", () => {
  expect(daysUntil(null, NOW)).toBeNull();
  expect(daysUntil("not-a-date", NOW)).toBeNull();
});

test("future date shows streams in Nd", () => {
  render(<CountdownBadge digitalDate="2026-08-22T00:00:00Z" now={NOW} />);
  expect(screen.getByTestId("countdown-badge")).toHaveTextContent("streams in 42d");
});

test("today shows streams today", () => {
  render(<CountdownBadge digitalDate="2026-07-11T00:00:00Z" now={NOW} />);
  expect(screen.getByTestId("countdown-badge")).toHaveTextContent("streams today");
});

test("past date shows streaming now", () => {
  render(<CountdownBadge digitalDate="2026-06-01T00:00:00Z" now={NOW} />);
  expect(screen.getByTestId("countdown-badge")).toHaveTextContent("streaming now");
});

test("missing date shows TBA", () => {
  render(<CountdownBadge digitalDate={null} now={NOW} />);
  expect(screen.getByTestId("countdown-badge")).toHaveTextContent("date TBA");
});
