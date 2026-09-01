import { type TabNavigationCategory } from "../types";
import { ReactComponent as CodeIcon } from "assets/code-02.svg?react";
import { ReactComponent as GuidedUnitIcon } from "assets/guided-unit-icon.svg?react";
import { ReactComponent as SystemToolsIcon } from "assets/code-browser.svg?react";
import { ReactComponent as VariablesIcon } from "assets/variable.svg?react";
import { ReactComponent as ShieldTickIcon } from "assets/shield-tick.svg?react";
import { ReactComponent as ShareIcon } from "assets/share-icon.svg?react";
import { ReactComponent as ClockCheckIcon } from "assets/clock-check.svg?react";

export const getToolsNavigations = (): TabNavigationCategory[] => [
  {
    key: "tools-root",
    category: "",
    title: "",
    paths: [
      { key: "apis", path: "apis", title: "APIs", enabled: true, icon: CodeIcon },
      { key: "guided-units", path: "guided-units", title: "Guided Units", enabled: true, icon: GuidedUnitIcon },
      { key: "system-tools", path: "system-tools", title: "System tools", enabled: true, icon: SystemToolsIcon },
    ],
  },
  {
    key: "variables",
    category: "",
    title: "",
    paths: [
      { key: "system-variables", path: "system-variables", title: "Platform variables", enabled: true, icon: VariablesIcon },
      { key: "share-convo-details", path: "share-convo-details", title: "Convo Ingestion Data", enabled: true, icon: ShareIcon },
      { key: "guardrails", path: "guardrails", title: "Guardrails", enabled: true, icon: ShieldTickIcon },
    ],
  },
  {
    key: "authentication",
    category: "",
    title: "",
    paths: [
      { key: "agent-time-zone", path: "agent-time-zone", title: "Agent time zone", enabled: true, icon: ClockCheckIcon },
    ],
  },
];
