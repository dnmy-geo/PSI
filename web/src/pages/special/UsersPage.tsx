import { resources } from '../../configs';
import { ResourcePage } from '../../components/resource';
import { UserPasswordAction } from '../../actions/UserPasswordAction';

export function UsersPage() {
  return <ResourcePage config={{ ...resources['system.users'],
    customAction: (row, _refresh, can) => can('update') ? <UserPasswordAction row={row} /> : null,
  }} />;
}

