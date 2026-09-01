import { AssistantRoute, type IAssistantNavigation } from "./types";
import { ReactComponent as AssistantBuildIcon } from "assets/assistant-build-icon.svg?react";
import { ReactComponent as AssistantToolsIcon } from "assets/assistant-tools-icon.svg?react";
import { ReactComponent as AssistantDeploymentIcon } from "assets/assistant-deployment-icon.svg?react";
import { ReactComponent as YpervainoIcon } from "assets/workflow.svg?react";

export const AssistantNavigations: IAssistantNavigation[] = [
  {
    label: "Build",
    key: AssistantRoute.OVERVIEW,
    icon: <AssistantBuildIcon />,
  },
  {
    label: "Deployment",
    key: AssistantRoute.DEPLOYMENT,
    icon: <AssistantDeploymentIcon />,
  },
  {
    label: "Tools & Settings",
    key: AssistantRoute.TOOLS,
    icon: <AssistantToolsIcon />,
  },
  {
    label: "Ypervaíno",
    key: AssistantRoute.YPERVAINO,
    icon: <YpervainoIcon />,
  },
];
