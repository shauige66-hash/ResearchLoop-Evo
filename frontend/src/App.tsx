import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Discovery from "./pages/Discovery";
import Library from "./pages/Library";
import Matrix from "./pages/Matrix";
import Report from "./pages/Report";
import Placeholder from "./pages/Placeholder";

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
          <Route
            path="/gaps"
            element={
              <Placeholder
                phase={2}
                title="Research Gap"
                description="Discover candidate research gaps from paper limitations and future work sections."
              />
            }
          />
          <Route
            path="/experiments"
            element={
              <Placeholder
                phase={3}
                title="Experiment Lab"
                description="Design and execute minimal viable experiments with independent verification."
              />
            }
          />
          <Route
            path="/evolution"
            element={
              <Placeholder
                phase={4}
                title="Evolution Lab"
                description="Extract skills from failure trajectories and iteratively improve agent capabilities."
              />
            }
          />
          <Route
            path="/skills"
            element={
              <Placeholder
                phase={5}
                title="Skill Registry"
                description="Version-controlled skill repository with independent evaluation and promotion gates."
              />
            }
          />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
