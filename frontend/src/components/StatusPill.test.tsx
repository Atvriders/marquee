import { render, screen } from "@testing-library/react";
import { StatusPill } from "./StatusPill";

test("renders plain label for ready", () => {
  render(<StatusPill status="ready" />);
  expect(screen.getByTestId("status-pill")).toHaveTextContent("ready");
});

test("renders percent for downloading", () => {
  render(<StatusPill status="downloading" pct={42.6} />);
  expect(screen.getByTestId("status-pill")).toHaveTextContent("downloading 43%");
});

test("downloading without pct omits percent", () => {
  render(<StatusPill status="downloading" />);
  expect(screen.getByTestId("status-pill")).toHaveTextContent("downloading");
  expect(screen.getByTestId("status-pill")).not.toHaveTextContent("%");
});

test("applies per-status class", () => {
  render(<StatusPill status="failed" />);
  expect(screen.getByTestId("status-pill").className).toContain("status-failed");
});
