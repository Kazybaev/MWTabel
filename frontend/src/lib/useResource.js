import { useCallback, useEffect, useRef, useState } from "react";

export function useResource(loader, deps) {
  const loaderRef = useRef(loader);
  const requestRef = useRef(0);
  const dependencyKey = JSON.stringify(deps);
  const [state, setState] = useState({
    data: null,
    error: "",
    loading: true,
    refreshing: false,
  });

  useEffect(() => {
    loaderRef.current = loader;
  });

  const load = useCallback(async () => {
    const requestId = ++requestRef.current;
    setState((currentState) => ({
      ...currentState,
      loading: currentState.data == null,
      refreshing: currentState.data != null,
      error: "",
    }));

    try {
      const data = await loaderRef.current();
      if (requestId !== requestRef.current) return;
      setState({
        data,
        error: "",
        loading: false,
        refreshing: false,
      });
    } catch (error) {
      if (requestId !== requestRef.current) return;
      setState((currentState) => ({
        ...currentState,
        error: error.message,
        loading: false,
        refreshing: false,
      }));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) load();
    });
    return () => {
      cancelled = true;
      requestRef.current += 1;
    };
  }, [dependencyKey, load]);

  return {
    ...state,
    reload: load,
    setData: (updater) => {
      setState((currentState) => ({
        ...currentState,
        data: typeof updater === "function" ? updater(currentState.data) : updater,
      }));
    },
  };
}
