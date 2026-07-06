import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router';
import { type Context, createContext, type JSX, type ReactNode, useContext } from 'react';

const TestChildrenContext: Context<ReactNode> = createContext<ReactNode>(null);

/**
 * Root component for the test router tree.
 * Defined at module scope to avoid the SonarQube "nested component definition"
 * warning that fires when components are defined inside render functions.
 */
function TestRouterRoot(): JSX.Element {
  const children = useContext(TestChildrenContext);
  return <>{children}</>;
}

/**
 * Wraps the given children in a minimal TanStack Router context backed by
 * an in-memory history. Pre-loads the router so that RouterProvider renders
 * content on the very first synchronous React render - without this, tests
 * see an empty DOM because RouterProvider waits for the async load to settle.
 *
 * Always `await` this before passing to `render()`:
 *   render(await wrapWithRouter(<MyComponent />))
 */
export async function wrapWithRouter(
  children: ReactNode,
  initialPath: string = '/',
): Promise<JSX.Element> {
  const rootRoute = createRootRoute({ component: TestRouterRoot });
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: [initialPath] }),
  });

  await router.load();

  return (
    <TestChildrenContext.Provider value={children}>
      <RouterProvider router={router} />
    </TestChildrenContext.Provider>
  );
}
