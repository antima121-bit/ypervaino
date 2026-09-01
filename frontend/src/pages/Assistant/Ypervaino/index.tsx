import TabHeader from "../components/TabHeader";
import { ReactComponent as YpervainoIcon } from "assets/workflow.svg?react";

const YPERVAINO_URL = "http://localhost:8765/";

const Ypervaino: React.FC = () => {
  return (
    <div
      style={{
        width: "100%",
        height: "calc(100vh - 144px)",
        display: "flex",
        flexDirection: "column",
        gap: "16px",
      }}
    >
      <TabHeader
        icon={<YpervainoIcon />}
        title="Ypervaíno"
        description="Evaluation studies for this assistant — before/after comparisons, session explorer, and results."
      />
      <div
        style={{
          flex: 1,
          minHeight: 0,
          border: "1px solid #E1DEDA",
          borderRadius: "8px",
          overflow: "hidden",
        }}
      >
        <iframe
          src={YPERVAINO_URL}
          title="Ypervaíno"
          style={{ width: "100%", height: "100%", border: "none", display: "block" }}
        />
      </div>
    </div>
  );
};

export default Ypervaino;
