import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { installFake } from "./test/server";
import { renderApp } from "./test/render";

describe("App shell", () => {
  it("renders the heading, nav and redirects / to /scope", async () => {
    installFake();
    const { router } = renderApp("/");
    expect(screen.getByRole("heading", { name: "Manual Labor" })).toBeInTheDocument();
    expect(await screen.findByTestId("group-tree")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/scope");
    const nav = screen.getByRole("navigation", { name: "Screens" });
    expect(nav).toHaveTextContent("Scope");
    expect(await screen.findByTestId("project-name")).toHaveTextContent("demo");
  });

  it("shows the Agent screen and NotFound", async () => {
    installFake();
    const { user, router } = renderApp("/scope");
    await screen.findByTestId("group-tree");
    await user.click(screen.getByRole("link", { name: "Agent" }));
    expect(await screen.findByTestId("agent-screen")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Back to Scope" }));
    expect(router.state.location.pathname).toBe("/scope");
    await router.navigate("/nope");
    expect(await screen.findByTestId("not-found")).toBeInTheDocument();
  });
});
