import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Discovery from "./pages/Discovery";
import Library from "./pages/Library";
import Matrix from "./pages/Matrix";
import Report from "./pages/Report";
import ResearchGap from "./pages/ResearchGap";
import ExperimentLab from "./pages/ExperimentLab";
import EvolutionLab from "./pages/EvolutionLab";
import SkillRegistry from "./pages/SkillRegistry";
import Workflow from "./pages/Workflow";
import Dossier from "./pages/Dossier";

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/discovery" element={<Discovery />} />
          <Route path="/library" element={<Library />} />
          <Route path="/matrix" element={<Matrix />} />
          <Route path="/report" element={<Report />} />
          <Route path="/gaps" element={<ResearchGap />} />
          <Route path="/experiments" element={<ExperimentLab />} />
          <Route path="/evolution" element={<EvolutionLab />} />
          <Route path="/skills" element={<SkillRegistry />} />
          <Route path="/workflow" element={<Workflow />} />
          <Route path="/dossier" element={<Dossier />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
