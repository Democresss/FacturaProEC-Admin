import React from 'react';

export function Card({ title, sub, icon, right, children }: {
  title?: React.ReactNode;
  sub?: React.ReactNode;
  icon?: React.ReactNode;
  right?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="card">
      {(title || right) && (
        <div className="row between mb-16">
          <div>
            {title && (
              <div className="card-title">
                {icon && <span>{icon}</span>}
                {title}
              </div>
            )}
            {sub && <div className="card-sub">{sub}</div>}
          </div>
          {right && <div>{right}</div>}
        </div>
      )}
      {children}
    </div>
  );
}
