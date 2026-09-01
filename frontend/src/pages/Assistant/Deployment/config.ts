import { type TabNavigationCategory } from "../types";
import { ReactComponent as ChatIcon } from "assets/chat-channel.svg?react";
import { ReactComponent as VoiceIcon } from "assets/voice-channel.svg?react";
import { ReactComponent as EyeIcon } from "assets/eye.svg?react";

export const DeploymentNavigations: TabNavigationCategory[] = [
  {
    key: "channels",
    category: "channels",
    title: "Channels",
    paths: [
      { key: "chat", path: "chat", title: "Chat", enabled: true, icon: ChatIcon },
      { key: "voice", path: "voice", title: "Voice", enabled: true, icon: VoiceIcon },
    ],
  },
  {
    key: "publish",
    category: "publish",
    title: "",
    paths: [
      { key: "publish-and-go-live", path: "publish-and-go-live", title: "Publish and go live", enabled: true, icon: ChatIcon },
    ],
  },
  {
    key: "embed",
    category: "embed",
    title: "",
    paths: [
      { key: "preview-and-share", path: "preview-and-share", title: "Preview & Share", enabled: true, icon: EyeIcon },
    ],
  },
];
