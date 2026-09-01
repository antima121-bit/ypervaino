import { ReactComponent as BotIcon } from "assets/bot.svg?react";
import { ReactComponent as PuzzleIcon } from "assets/puzzle-piece-02 (4).svg?react";
import { ReactComponent as AnalyticsIcon } from "assets/analytics.svg?react";
import { ReactComponent as OutboundCampaignIcon } from "assets/outbound-campaign-icon.svg?react";

const NavigationItems = [
  {
    key: "assistant",
    path: "assistant",
    title: "Agents",
    icon: BotIcon,
    enable: true,
  },
  {
    key: "outbound-campaign",
    path: "outbound-campaign",
    title: "Outbound campaigns",
    icon: OutboundCampaignIcon,
    enable: true,
  },
  {
    key: "connectors-flow",
    path: "integrations",
    title: "Integrations",
    icon: PuzzleIcon,
    enable: true,
  },
  {
    key: "analytics",
    path: "analytics",
    title: "Analytics",
    icon: AnalyticsIcon,
    enable: true,
  },
];

export default NavigationItems;
