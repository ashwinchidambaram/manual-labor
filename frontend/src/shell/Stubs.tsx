import { Link } from "react-router-dom";

export function ComingSoon({ name }: { name: string }) {
  return (
    <main className="p-6" data-testid={`stub-${name.toLowerCase()}`}>
      <h2 className="text-xl font-semibold">{name}</h2>
      <p className="my-2 text-slate-600">This screen arrives in a later module.</p>
      <Link className="text-blue-700 underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600" to="/scope">
        Back to Scope
      </Link>
    </main>
  );
}

export function NotFound() {
  return (
    <main className="p-6" data-testid="not-found">
      <h2 className="text-xl font-semibold">Page not found</h2>
      <Link className="text-blue-700 underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600" to="/scope">
        Go to Scope
      </Link>
    </main>
  );
}
