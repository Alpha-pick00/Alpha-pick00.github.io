import React, { createContext, useContext, useState } from 'react';

// 사이드바 열림 상태를 Sidebar 바깥(App의 레이아웃 padding, Hero의 고정 로고 위치)에서도
// 알아야 해서(2026-08-12: "옆으로 반응형으로 가게") 이 상태를 Sidebar 로컬이 아니라
// context로 끌어올렸다 - App이 이걸 보고 본문 padding을 넓혀 사이드바를 "덮는" 모달이
// 아니라 "밀어내는" 도크로 만든다.
interface SidebarContextValue {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  toggle: () => void;
}

const SidebarContext = createContext<SidebarContextValue | null>(null);

export const SidebarProvider = ({ children }: { children: React.ReactNode }) => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <SidebarContext.Provider
      value={{
        isOpen,
        open: () => setIsOpen(true),
        close: () => setIsOpen(false),
        toggle: () => setIsOpen((prev) => !prev),
      }}
    >
      {children}
    </SidebarContext.Provider>
  );
};

export const useSidebar = () => {
  const ctx = useContext(SidebarContext);
  if (!ctx) throw new Error('useSidebar는 SidebarProvider 내부에서만 사용할 수 있습니다.');
  return ctx;
};
