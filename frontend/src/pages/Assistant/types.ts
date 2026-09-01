export enum AssistantRoute {
  OVERVIEW = "overview",
  DEPLOYMENT = "deployment",
  TOOLS = "tools",
  YPERVAINO = "ypervaino",
}

export interface IAssistantNavigation {
  label: string;
  key: AssistantRoute;
  icon: React.ReactNode;
}

export interface TabNavigationPath {
  key: string;
  path: string;
  title: string;
  enabled: boolean;
  icon?: React.FC<React.SVGProps<SVGSVGElement>>;
}

export interface TabNavigationCategory {
  key: string;
  category: string;
  title: string;
  paths: TabNavigationPath[];
}

export enum OrchestrationType {
  DELEGATOR_V2_VOICE = "DELEGATOR_V2_VOICE",
  SIMPLE = "SIMPLE",
  DIALOG_FLOW = "DIALOG_FLOW",
  SINGLE_AGENT = "SINGLE_AGENT",
  MULTI_AGENT = "MULTI_AGENT",
  WORKFLOW_AGENT = "WORKFLOW_AGENT",
}
