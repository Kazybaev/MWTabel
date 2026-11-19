import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

export function useResource(loader, deps) {
  const [state, setState] = useState({
    data: null,
    error: "",
    loading: true,
    refreshing: false,
  });

  const requestId = useRef(0);
  const latestLoader = useRef(loader);
  useLayoutEffect(() => {
    latestLoader.current = loader;
  }, [loader]);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setState((currentState) => ({
      ...currentState,
      loading: currentState.data == null,
      refreshing: currentState.data != null,
      error: "",
    }));

    try {
      const data = await latestLoader.current();
      if (id !== requestId.current) return;
      setState({
        data,
        error: "",
        loading: false,
        refreshing: false,
      });
    } catch (error) {
      if (id !== requestId.current) return;
      setState((currentState) => ({
        ...currentState,
        error: error.message,
        loading: false,
        refreshing: false,
      }));
    }
  }, []);

  useEffect(() => {
    load();
    return () => { requestId.current += 1; };
    // Callers supply the resource identity and decide when it should be fetched.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const setData = useCallback((updater) => {
    setState((currentState) => ({
      ...currentState,
      data: typeof updater === "function" ? updater(currentState.data) : updater,
    }));
  }, []);

  return {
    ...state,
    reload: load,
    setData,
  };
}
