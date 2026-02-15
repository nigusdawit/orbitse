import { Switch, Route } from "wouter";
import { queryClient } from "./lib/queryClient";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/not-found";
import Home from "@/pages/home";

function CasaSerena() {
  return <Home siteId="casa-serena" />;
}

function Velocity() {
  return <Home siteId="velocity" />;
}

function Router() {
  return (
    <Switch>
      <Route path="/" component={CasaSerena} />
      <Route path="/velocity" component={Velocity} />
      <Route component={NotFound} />
    </Switch>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Router />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;
